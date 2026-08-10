import {
  DEFAULT_PRODUCT_CUTOUT,
  MOCK_EDITOR_LAYERS,
} from "@/lib/constants/mock-editor"
import type { AuthTokens, AuthUser } from "@/lib/auth/session"
import type { CanvasLayer } from "@/types/canvas"

/**
 * Client-side mock mode. Set `NEXT_PUBLIC_IS_MOCK=true` in env.
 * When enabled: auto-login, no real API for generate/SEO/auth profile.
 */
export const IS_MOCK =
  process.env.NEXT_PUBLIC_IS_MOCK === "true" ||
  process.env.NEXT_PUBLIC_IS_MOCK === "1"

/** Public card / product assets used as fake generate results. */
export const MOCK_CARD_IMAGE = "/projects/cream-sage-mist.png"
export const MOCK_PRODUCT_IMAGE = DEFAULT_PRODUCT_CUTOUT

export const MOCK_GENERATE_DELAY_MS = 2500

/** Minimal identity requested for mock login. */
export const mockUser = {
  id: 1,
  email: "test@admin.com",
} as const

export const MOCK_AUTH_USER: AuthUser = {
  id: String(mockUser.id),
  email: mockUser.email,
  ai_coins: 999,
  subscription_status: "pro",
  is_admin: true,
  created_at: "2026-01-01T00:00:00.000Z",
}

export const MOCK_AUTH_TOKENS: AuthTokens = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
}

export type MockSeoResult = {
  optimized_title: string
  benefits: string[]
  description: string
}

/** Prepared SEO copy + benefit chips for UI walkthrough. */
export const MOCK_SEO_RESULT: MockSeoResult = {
  optimized_title:
    "Крем для рук Sage Mist 75 мл — эко-формула, увлажнение 24ч",
  benefits: [
    "Эко-формула без парабенов",
    "Увлажнение кожи до 24 часов",
    "Лёгкая текстура, быстрое впитывание",
    "Подходит для ежедневного ухода",
    "Натуральные экстракты шалфея",
  ],
  description:
    "Sage Mist — крем для рук с натуральными экстрактами шалфея и питательными маслами " +
    "для ежедневного ухода за сухой и чувствительной кожей. Формула без парабенов мягко " +
    "увлажняет, восстанавливает защитный барьер и помогает справиться с стянутостью после " +
    "мытья рук и работы в помещении с сухим воздухом. Лёгкая текстура быстро впитывается, " +
    "не оставляя липкой плёнки, поэтому крем удобно брать с собой в сумку и наносить в " +
    "течение дня. Подходит тем, кто ищет увлажняющий крем для рук с эко-составом, свежим " +
    "ароматом и заметным эффектом мягкости уже после первого применения. Объём 75 мл — " +
    "оптимальный формат для дома и поездок. Выбирайте Sage Mist, если хотите закрыть " +
    "боль сухой кожи, снизить раздражение от частого мытья и получить предсказуемый " +
    "результат ухода без тяжёлых отдушек и ощущения липкости на коже.",
}

/** Deep-cloned clean editor layers: background + product cutout only. */
export function getMockGenerateLayers(): CanvasLayer[] {
  return structuredClone(MOCK_EDITOR_LAYERS)
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

/** Billing period keys used by TopUpDialog / Pricing tabs. */
export type MockBillingPeriod = "week" | "month" | "half_year" | "year"

export type MockTopUpPlan = {
  id: string
  /** Must match period tab ids: week | month | half_year | year */
  period: MockBillingPeriod
  /** Backend tariff code for YooKassa checkout */
  tariffCode: "start" | "pro" | "half_year" | "year"
  name: string
  priceRub: number
  periodLabel: string
  coins: number
  features: string[]
  /** Shown for subscriptions from 6 months */
  advantageous?: boolean
}

/** Mock tariffs for «Пополнить баланс» — one plan per period tab. */
export const MOCK_TOP_UP_PLANS: MockTopUpPlan[] = [
  {
    id: "topup-week",
    period: "week",
    tariffCode: "start",
    name: "Pro Lite",
    priceRub: 490,
    periodLabel: "1 неделя",
    coins: 45,
    features: [
      "45 ИИ-монет на генерации",
      "Умная AI-вырезка товара",
      "Виртуальный софтбокс и студийный свет",
      "Экспорт в HD для Ozon и WB",
      "Генерация инфографики и плашек",
    ],
  },
  {
    id: "topup-month",
    period: "month",
    tariffCode: "pro",
    name: "Pro",
    priceRub: 1490,
    periodLabel: "1 месяц",
    coins: 200,
    features: [
      "200 ИИ-монет в месяц",
      "Умная AI-вырезка товара",
      "Виртуальный софтбокс и студийный свет",
      "Экспорт в HD для Ozon и WB",
      "Генерация инфографики и плашек",
      "Приоритет в очереди рендера",
    ],
  },
  {
    id: "topup-half-year",
    period: "half_year",
    tariffCode: "half_year",
    name: "Business",
    priceRub: 6900,
    periodLabel: "6 месяцев",
    coins: 1200,
    advantageous: true,
    features: [
      "1 200 ИИ-монет на полгода",
      "Авто-SEO описаний карточек",
      "Сканер конкурентов и парсер",
      "Smart SEO и закрытие негатива",
      "Все возможности Pro",
      "Пакетный рендер",
    ],
  },
  {
    id: "topup-year",
    period: "year",
    tariffCode: "year",
    name: "Business",
    priceRub: 11900,
    periodLabel: "1 год",
    coins: 3000,
    advantageous: true,
    features: [
      "3 000 ИИ-монет на год",
      "Приоритетный рендер Ultra-HD",
      "Личный парсер конкурентов",
      "VIP-поддержка в Telegram",
      "Авто-SEO и закрытие негатива",
      "Все возможности Business 6 мес.",
    ],
  },
]
