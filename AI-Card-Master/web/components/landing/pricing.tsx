"use client"

import { Check, Sparkles } from "lucide-react"
import { useRouter } from "next/navigation"
import { useMemo, useRef, useState } from "react"
import { AnimatePresence, motion, useInView } from "framer-motion"

import { GlassButton } from "@/components/ui/glass-button"
import { GlassCard } from "@/components/ui/glass-card"
import { SectionHeader } from "@/components/ui/section-header"
import { cn } from "@/lib/utils"

type BillingPeriod = "week" | "month" | "half_year" | "year"

type PricingPlan = {
  id: string
  period: BillingPeriod
  name: string
  priceRub: number
  periodLabel: string
  coins: number
  coinsNote: string
  blurb: string
  features: string[]
  cta: string
  href: string
  highlighted?: boolean
  badge?: string
}

const PERIODS: { id: BillingPeriod; label: string }[] = [
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "half_year", label: "6 Месяцев" },
  { id: "year", label: "1 Год" },
]

const PLANS: PricingPlan[] = [
  {
    id: "start",
    period: "week",
    name: "Start",
    priceRub: 0,
    periodLabel: "1 неделя",
    coins: 5,
    coinsNote: "приветственных монет",
    blurb:
      "Бесплатный вход на 1 неделю: базовая AI-вырезка и экспорт под маркетплейсы, чтобы протестировать систему.",
    features: [
      "5 приветственных ИИ-монет",
      "Базовый рендер карточки",
      "Умная AI-вырезка товара",
      "Виртуальный софтбокс и студийный свет",
      "Экспорт в HD для Ozon и WB",
    ],
    cta: "Начать бесплатно",
    href: "/register",
  },
  {
    id: "pro-week",
    period: "week",
    name: "Pro Lite",
    priceRub: 319,
    periodLabel: "1 неделя",
    coins: 45,
    coinsNote: "ИИ-монет",
    blurb:
      "Быстрый тест — разовые поставки и точечные обновления плашек без долгой подписки.",
    features: [
      "45 ИИ-монет на генерации",
      "Умная AI-вырезка товара",
      "Виртуальный софтбокс и студийный свет",
      "Экспорт в HD для Ozon и WB",
      "Генерация инфографики и плашек",
    ],
    cta: "Взять Pro Lite",
    href: "/register",
    badge: "Быстрый тест",
  },
  {
    id: "pro-month",
    period: "month",
    name: "Pro",
    priceRub: 990,
    periodLabel: "1 месяц",
    coins: 200,
    coinsNote: "ИИ-монет",
    blurb:
      "Основной тариф — студийный свет, умная вырезка и инфографика в одном пайплайне.",
    features: [
      "200 ИИ-монет в месяц",
      "Умная AI-вырезка товара",
      "Виртуальный софтбокс и студийный свет",
      "Экспорт в HD для Ozon и WB",
      "Генерация инфографики и плашек",
      "Приоритет в очереди рендера",
    ],

    cta: "Выбрать Pro",
    href: "/register",
    highlighted: true,
    badge: "Основной тариф",
  },
  {
    id: "business-half",
    period: "half_year",
    name: "Business",
    priceRub: 5990,
    periodLabel: "6 месяцев",
    coins: 1200,
    coinsNote: "ИИ-монет",
    blurb:
      "Масштабирование — авто-SEO, сканер конкурентов и расширенный баланс монет для растущих брендов.",
    features: [
      "1 200 ИИ-монет на полгода",
      "Авто-SEO описаний карточек",
      "Сканер конкурентов и парсер",
      "Smart SEO и закрытие негатива",
      "Все возможности Pro",
      "Расширенный баланс и пакетный рендер",
    ],
    cta: "Подключить Business",
    href: "/register",
    badge: "Масштабирование",
  },
  {
    id: "business-year",
    period: "year",
    name: "Business",
    priceRub: 8990,
    periodLabel: "1 год",
    coins: 3000,
    coinsNote: "ИИ-монет",
    blurb:
      "Масштабирование — приоритетный рендер, личный парсер и VIP-поддержка для студий с большим SKU.",
    features: [
      "3 000 ИИ-монет на год",
      "Приоритетный рендер Ultra-HD",
      "Личный парсер конкурентов",
      "VIP-поддержка в Telegram",
      "Авто-SEO и закрытие негатива",
      "Все возможности Business 6 мес.",
    ],
    cta: "Взять на год",
    href: "/register",
    badge: "Масштабирование",
  },
]

function formatPrice(value: number): string {
  if (value === 0) return "0"
  return new Intl.NumberFormat("ru-RU").format(value)
}

function PricingCard({
  plan,
  inView,
  index,
}: {
  plan: PricingPlan
  inView: boolean
  index: number
}) {
  const router = useRouter()

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 24 }}
      animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 24 }}
      exit={{ opacity: 0, y: 12, scale: 0.98 }}
      transition={{
        duration: 0.45,
        delay: 0.06 * index,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={cn(
        "relative h-full",
        plan.highlighted && "z-[1] sm:-mt-2 sm:mb-2"
      )}
    >
      {plan.badge ? (
        <span className="absolute -top-3 left-1/2 z-10 -translate-x-1/2 rounded-md border border-white/20 bg-loft-surface px-3 py-1 font-heading text-[11px] font-semibold tracking-wide text-foreground uppercase">
          {plan.badge}
        </span>
      ) : null}

      <GlassCard
        className={cn(
          "relative flex h-full flex-col overflow-hidden",
          plan.highlighted && "border-white/25 shadow-panel"
        )}
        padding="lg"
        hoverLift={!plan.highlighted}
      >
        {plan.highlighted ? (
          <div
            className="pointer-events-none absolute inset-0 bg-white/[0.02]"
            aria-hidden
          />
        ) : null}

        <div className="relative flex flex-1 flex-col">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="font-heading text-xl font-semibold tracking-tight text-foreground">
              {plan.name}
            </h3>
            <span className="font-heading text-[11px] tracking-wide text-text-muted uppercase">
              {plan.periodLabel}
            </span>
          </div>

          <p className="mt-3 text-sm leading-relaxed text-text-muted">
            {plan.blurb}
          </p>

          <div className="mt-6 flex items-end gap-1.5">
            <span className="font-heading text-4xl font-semibold tracking-tight text-foreground tabular-nums">
              {formatPrice(plan.priceRub)}
            </span>
            <span className="mb-1.5 text-sm text-text-muted">₽</span>
          </div>

          <div className="mt-3 inline-flex w-fit items-center gap-2 rounded-lg border border-white/12 bg-white/[0.04] px-3 py-1.5">
            <Sparkles className="size-3.5 text-muted-foreground" aria-hidden />
            <span className="font-heading text-sm font-medium text-foreground">
              {new Intl.NumberFormat("ru-RU").format(plan.coins)}{" "}
              {plan.coinsNote}
            </span>
          </div>

          <ul className="mt-6 flex flex-col gap-2.5">
            {plan.features.map((feature) => (
              <li
                key={feature}
                className="flex items-start gap-2.5 text-sm leading-snug text-text-muted"
              >
                <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border border-white/12 bg-white/[0.04] text-foreground">
                  <Check className="size-3" strokeWidth={2.5} aria-hidden />
                </span>
                <span>{feature}</span>
              </li>
            ))}
          </ul>

          <div className="mt-8 flex-1" />

          <GlassButton
            className={cn(
              "w-full",
              !plan.highlighted &&
                "border border-white/12 bg-transparent text-foreground hover:bg-white/[0.04]"
            )}
            onClick={() => router.push(plan.href)}
          >
            {plan.cta}
          </GlassButton>
        </div>
      </GlassCard>
    </motion.div>
  )
}

function PricingSection() {
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.15 })
  const [period, setPeriod] = useState<BillingPeriod>("month")

  const visiblePlans = useMemo(
    () => PLANS.filter((plan) => plan.period === period),
    [period]
  )

  return (
    <section
      id="pricing"
      ref={sectionRef}
      className="relative isolate scroll-mt-24 py-16 md:py-24"
    >
      <div className="mx-auto max-w-6xl px-5">
        <div className="section-glass flex flex-col gap-12 rounded-3xl px-5 py-10 sm:px-8 sm:py-12 lg:px-10">
          <SectionHeader
            align="center"
            title="Тарифы"
            subtitle="Start → Pro Lite → Pro → Business. Выберите период: 1 генерация = 1 ИИ-монета."
          />

          <div className="flex flex-col gap-8">
          <div
            role="tablist"
            aria-label="Период подписки"
            className="mx-auto flex w-full max-w-xl flex-wrap justify-center gap-1 rounded-xl border border-white/10 bg-loft p-1.5"
          >
            {PERIODS.map((item) => {
              const active = period === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setPeriod(item.id)}
                  className={cn(
                    "relative min-w-[5.5rem] flex-1 rounded-lg px-3 py-2.5 font-heading text-sm font-medium transition-colors",
                    active
                      ? "text-foreground"
                      : "text-text-muted hover:text-foreground/80"
                  )}
                >
                  {active ? (
                    <motion.span
                      layoutId="pricing-period-pill"
                      className="absolute inset-0 rounded-lg border border-white/12 bg-white/[0.06]"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  ) : null}
                  <span className="relative z-[1]">{item.label}</span>
                </button>
              )
            })}
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={period}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "mx-auto grid gap-5",
                visiblePlans.length === 1 && "max-w-md",
                visiblePlans.length === 2 && "max-w-3xl sm:grid-cols-2",
                visiblePlans.length >= 3 && "sm:grid-cols-2 lg:grid-cols-3"
              )}
            >
              {visiblePlans.map((plan, i) => (
                <PricingCard
                  key={plan.id}
                  plan={plan}
                  inView={inView}
                  index={i}
                />
              ))}
            </motion.div>
          </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  )
}

export { PricingSection }
