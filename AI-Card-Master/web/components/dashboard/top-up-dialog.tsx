"use client"

import { Check, Sparkles } from "lucide-react"
import Link from "next/link"
import { useMemo, useState } from "react"

import { buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { GlassButton } from "@/components/ui/glass-button"
import { cn } from "@/lib/utils"

type BillingPeriod = "week" | "month" | "half_year" | "year"

type TopUpPlan = {
  id: string
  period: BillingPeriod
  name: string
  priceRub: number
  coins: number
  highlighted?: boolean
}

const PERIODS: { id: BillingPeriod; label: string }[] = [
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "half_year", label: "6 мес." },
  { id: "year", label: "Год" },
]

const TOP_UP_PLANS: TopUpPlan[] = [
  {
    id: "start",
    period: "week",
    name: "Start",
    priceRub: 0,
    coins: 5,
  },
  {
    id: "pro-week",
    period: "week",
    name: "Pro Lite",
    priceRub: 319,
    coins: 45,
  },
  {
    id: "pro-month",
    period: "month",
    name: "Pro",
    priceRub: 990,
    coins: 200,
    highlighted: true,
  },
  {
    id: "business-half",
    period: "half_year",
    name: "Business",
    priceRub: 5990,
    coins: 1200,
  },
  {
    id: "business-year",
    period: "year",
    name: "Business",
    priceRub: 8990,
    coins: 3000,
    highlighted: true,
  },
]

function formatPrice(value: number): string {
  if (value === 0) return "0"
  return new Intl.NumberFormat("ru-RU").format(value)
}

type TopUpDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function TopUpDialog({ open, onOpenChange }: TopUpDialogProps) {
  const [period, setPeriod] = useState<BillingPeriod>("month")

  const plans = useMemo(
    () => TOP_UP_PLANS.filter((plan) => plan.period === period),
    [period]
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(90dvh,40rem)] w-full overflow-y-auto sm:max-w-lg"
        showCloseButton
      >
        <DialogHeader>
          <DialogTitle>Пополнить баланс</DialogTitle>
          <DialogDescription>
            Выберите тариф — 1 генерация = 1 ИИ-монета
          </DialogDescription>
        </DialogHeader>

        <div
          role="tablist"
          aria-label="Период подписки"
          className="flex flex-wrap gap-1 rounded-xl border border-white/8 bg-loft/60 p-1"
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
                  "min-w-[4.5rem] flex-1 rounded-lg px-2 py-2 font-heading text-xs font-medium transition-colors sm:text-sm",
                  active
                    ? "bg-emerald/15 text-foreground ring-1 ring-emerald/35"
                    : "text-text-muted hover:text-foreground/80"
                )}
              >
                {item.label}
              </button>
            )
          })}
        </div>

        <ul className="space-y-2">
          {plans.map((plan) => (
            <li key={plan.id}>
              <button
                type="button"
                className={cn(
                  "flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors",
                  plan.highlighted
                    ? "border-emerald/40 bg-emerald/10"
                    : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05]"
                )}
                onClick={() => onOpenChange(false)}
              >
                <span
                  className={cn(
                    "flex size-8 shrink-0 items-center justify-center rounded-lg",
                    plan.highlighted
                      ? "bg-emerald/20 text-emerald"
                      : "bg-white/5 text-copper"
                  )}
                >
                  {plan.highlighted ? (
                    <Sparkles className="size-4" aria-hidden />
                  ) : (
                    <Check className="size-4" aria-hidden />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-heading text-sm font-semibold text-foreground">
                    {plan.name}
                  </span>
                  <span className="block text-xs text-text-muted">
                    {new Intl.NumberFormat("ru-RU").format(plan.coins)} монет
                  </span>
                </span>
                <span className="font-heading text-sm font-semibold tabular-nums text-foreground">
                  {formatPrice(plan.priceRub)} ₽
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
          <Link
            href="/pricing"
            onClick={() => onOpenChange(false)}
            className={cn(
              buttonVariants({ variant: "outline" }),
              "border-white/10 bg-transparent"
            )}
          >
            Все тарифы
          </Link>
          <GlassButton type="button" onClick={() => onOpenChange(false)}>
            Продолжить
          </GlassButton>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export { TopUpDialog }
