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

/** Delay for Eye of God spy enqueue/poll demo. */
export const MOCK_EYE_OF_GOD_DELAY_MS = 1100

export type MockEyeOfGodFrequencyItem = {
  text: string
  count: number
  share_percent: number
  examples?: string[]
}

export type MockEyeOfGodCompetitor = {
  rank: number
  article: string
  marketplace: string
  title?: string | null
  brand?: string | null
  url?: string | null
  price_rub?: number | null
  feedbacks?: number | null
  estimated_purchases?: number | null
  estimated_revenue_rub?: number | null
  is_niche_revenue_leader?: boolean
  conversion_triggers?: string[]
  weaknesses?: string[]
  advice_reliability_pct?: number
}

export type MockBuyerPain = {
  rank: number
  title: string
  summary: string
  evidence_quotes: string[]
}

export type MockInfographicOffer = {
  pain_rank: number
  offer_text: string
}

export type MockCompetitorPains = {
  pains: MockBuyerPain[]
  recommendations: MockInfographicOffer[]
  provider: string
  model_name: string
  input_tokens: number
  output_tokens: number
}

export type MockEyeOfGodDashboard = {
  schema_version: string
  seed_article: string
  seed_marketplace: string
  seed_title: string
  competitors_analyzed: number
  competitors: MockEyeOfGodCompetitor[]
  badge_patterns: MockEyeOfGodFrequencyItem[]
  strong_triggers: MockEyeOfGodFrequencyItem[]
  frequent_keywords: MockEyeOfGodFrequencyItem[]
  visual_hooks: string[]
  ai_recommendation: string
  generator_prompt: string
  notes?: string[]
}

/** Demo spy dashboard for «Глаз Бога» in mock mode. */
export const MOCK_EYE_OF_GOD_DASHBOARD: MockEyeOfGodDashboard = {
  schema_version: "1.0",
  seed_article: "178902345",
  seed_marketplace: "wildberries",
  seed_title: "Крем для рук Sage Mist 75 мл",
  competitors_analyzed: 10,
  competitors: [
    {
      rank: 1,
      article: "178902345",
      marketplace: "wildberries",
      title: "Крем для рук Sage Mist 75 мл",
      brand: "Sage Mist",
      url: "https://www.wildberries.ru/catalog/178902345/detail.aspx",
      price_rub: 590,
      feedbacks: 3200,
      estimated_purchases: 40000,
      estimated_revenue_rub: 23_600_000,
      is_niche_revenue_leader: true,
      conversion_triggers: ["24ч увлажнение", "Эко-формула"],
      weaknesses: ["Нет до/после на первом слайде"],
      advice_reliability_pct: 84,
    },
    {
      rank: 2,
      article: "201145678",
      marketplace: "wildberries",
      title: "Крем для рук увлажняющий 100 мл",
      brand: "HydraLab",
      price_rub: 449,
      feedbacks: 1800,
      estimated_purchases: 22500,
      estimated_revenue_rub: 10_102_500,
      is_niche_revenue_leader: false,
      conversion_triggers: ["До/после", "Без парабенов"],
      weaknesses: ["Мелкий шрифт оффера"],
      advice_reliability_pct: 78,
    },
    {
      rank: 3,
      article: "199887766",
      marketplace: "wildberries",
      title: "Крем для рук с маслом ши",
      brand: "SoftCare",
      price_rub: 520,
      feedbacks: 950,
      estimated_purchases: 11875,
      estimated_revenue_rub: 6_175_000,
      is_niche_revenue_leader: false,
      conversion_triggers: ["Питание 12ч", "Быстро впитывается"],
      weaknesses: ["Слабый контраст плашек"],
      advice_reliability_pct: 71,
    },
    {
      rank: 4,
      article: "188776655",
      marketplace: "wildberries",
      title: "Крем-бальзам для сухой кожи рук",
      brand: "Dermolux",
      price_rub: 390,
      feedbacks: 720,
      estimated_purchases: 9000,
      estimated_revenue_rub: 3_510_000,
      is_niche_revenue_leader: false,
      conversion_triggers: ["Аптечный уход", "Заживление трещин"],
      weaknesses: ["Нет оффера на объём"],
      advice_reliability_pct: 66,
    },
    {
      rank: 5,
      article: "167554433",
      marketplace: "wildberries",
      title: "Крем для рук с мочевиной 10%",
      brand: "UreaCare",
      price_rub: 610,
      feedbacks: 540,
      estimated_purchases: 6750,
      estimated_revenue_rub: 4_117_500,
      is_niche_revenue_leader: false,
      conversion_triggers: ["Мочевина 10%", "Для трещин"],
      weaknesses: ["Слабый первый слайд"],
      advice_reliability_pct: 62,
    },
  ],
  badge_patterns: [
    {
      text: "Без парабенов",
      count: 7,
      share_percent: 70,
      examples: ["Без парабенов", "0% парабенов"],
    },
    {
      text: "24ч увлажнение",
      count: 5,
      share_percent: 50,
      examples: ["Увлажнение 24 часа"],
    },
    {
      text: "Быстро впитывается",
      count: 4,
      share_percent: 40,
    },
  ],
  strong_triggers: [
    {
      text: "До/после",
      count: 6,
      share_percent: 60,
    },
    {
      text: "Эко-формула",
      count: 5,
      share_percent: 50,
    },
    {
      text: "Гарантия результата",
      count: 3,
      share_percent: 30,
    },
  ],
  frequent_keywords: [
    { text: "увлажнение", count: 9, share_percent: 90 },
    { text: "крем", count: 10, share_percent: 100 },
    { text: "рук", count: 10, share_percent: 100 },
    { text: "шалфей", count: 4, share_percent: 40 },
    { text: "питание", count: 5, share_percent: 50 },
  ],
  visual_hooks: [
    "Оффер слева + продукт справа на светлом фоне",
    "Контрастные amber-плашки на тёмном loft",
    "Слепая зона: состав не вынесен на первый слайд",
    "Палитра: #0f172a / #f59e0b / #f8fafc",
  ],
  ai_recommendation:
    "Соберите первый слайд сильнее ТОП-10: крупный оффер «24ч увлажнение», " +
    "плашки «Без парабенов» и «Быстро впитывается», схема до/после и закрытие " +
    "слепой зоны по составу. Фон — светлый loft с мягким софтбоксом слева, " +
    "контраст текста выше, чем у HydraLab и SoftCare.",
  generator_prompt:
    "Marketplace card, hand cream bottle hero on light loft background, softbox from left, " +
    "bold Russian badges: «24ч увлажнение», «Без парабенов», «Быстро впитывается», " +
    "before/after strip, high contrast amber accents, no competitor logos",
  notes: ["mock_demo"],
}

/** Demo LLM pains + badge offers for «Глаз Бога» niche analysis. */
export const MOCK_COMPETITOR_PAINS: MockCompetitorPains = {
  pains: [
    {
      rank: 1,
      title: "Жидкая текстура, стекает с рук",
      summary:
        "Покупатели жалуются, что крем слишком жидкий и не остаётся на коже — ощущение «напрасно намазал».",
      evidence_quotes: [
        "жидкий, стекает с рук",
        "как вода, ничего не остаётся",
      ],
    },
    {
      rank: 2,
      title: "Химический / резкий запах",
      summary:
        "Негатив по отдушке: «пахнет аптекой», «химия», из‑за запаха товар не донашивают.",
      evidence_quotes: ["плохо пахнет химией", "резкий запах"],
    },
    {
      rank: 3,
      title: "Слабое увлажнение — эффект не держится",
      summary:
        "Через 30–60 минут кожа снова сухая; ожидают «24ч» и не получают.",
      evidence_quotes: [
        "не увлажняет, кожа снова сухая через час",
        "эффект на полчаса",
      ],
    },
  ],
  recommendations: [
    {
      pain_rank: 1,
      offer_text: "Густая текстура — не стекает",
    },
    {
      pain_rank: 2,
      offer_text: "Мягкий аромат без химии",
    },
    {
      pain_rank: 3,
      offer_text: "Увлажнение до 24 часов",
    },
  ],
  provider: "mock",
  model_name: "mock-pains",
  input_tokens: 0,
  output_tokens: 0,
}

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

/** Deep-cloned editor layers: product cutout + SEO-style title/subtitle + feature badges. */
export function getMockGenerateLayers(): CanvasLayer[] {
  return structuredClone(MOCK_EDITOR_LAYERS).map((layer) => {
    if (layer.id === "layer_title") {
      return {
        ...layer,
        text: "Sage Mist",
      }
    }
    if (layer.id === "layer_subtitle") {
      return {
        ...layer,
        text: "Крем для рук · SEO-карточка",
      }
    }
    return layer
  })
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
