"use client"

import { Check, Loader2, Sparkles } from "lucide-react"
import Link from "next/link"
import { useMemo, useState } from "react"
import { toast } from "sonner"

import { buttonVariants } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { GlassButton } from "@/components/ui/glass-button"
import { GlassCard } from "@/components/ui/glass-card"
import {
  createPayment,
  getApiErrorMessage,
  type TariffCode,
} from "@/lib/api"
import {
  IS_MOCK,
  MOCK_TOP_UP_PLANS,
  type MockBillingPeriod,
} from "@/lib/constants/mock"
import { cn } from "@/lib/utils"

type BillingPeriod = MockBillingPeriod

const PERIODS: { id: BillingPeriod; label: string }[] = [
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "half_year", label: "6 мес." },
  { id: "year", label: "Год" },
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
  const [checkoutCode, setCheckoutCode] = useState<string | null>(null)

  // Filter by plan.period (not tariff code) so every tab has cards.
  const plans = useMemo(
    () => MOCK_TOP_UP_PLANS.filter((plan) => plan.period === period),
    [period]
  )

  const handleCheckout = async (tariffCode: TariffCode) => {
    if (checkoutCode) return
    setCheckoutCode(tariffCode)
    try {
      if (IS_MOCK) {
        await new Promise((resolve) => setTimeout(resolve, 400))
        toast.success(`Mock: выбран тариф «${tariffCode}»`)
        onOpenChange(false)
        return
      }
      const payment = await createPayment(tariffCode)
      if (!payment.confirmation_url) {
        toast.error(
          "Платёжный провайдер недоступен: confirmation_url не получен. Проверьте YOOKASSA_*."
        )
        return
      }
      window.location.assign(payment.confirmation_url)
    } catch (error) {
      toast.error(
        getApiErrorMessage(
          error,
          "Не удалось создать платёж. Проверьте настройки YooKassa."
        )
      )
    } finally {
      setCheckoutCode(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(90dvh,44rem)] w-full overflow-y-auto sm:max-w-xl"
        showCloseButton
      >
        <DialogHeader>
          <DialogTitle>Пополнить баланс</DialogTitle>
          <DialogDescription>
            Выберите тариф — 1 генерация = 1 ИИ-монета. Оплата через YooKassa.
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

        {plans.length === 0 ? (
          <p className="rounded-xl border border-amber/30 bg-amber/10 px-3 py-4 text-sm text-foreground">
            Для выбранного периода нет доступных тарифов.
          </p>
        ) : (
          <ul className="space-y-3">
            {plans.map((plan) => {
              const busy = checkoutCode === plan.tariffCode
              return (
                <li key={plan.id} className="relative">
                  {plan.advantageous ? (
                    <span className="absolute -top-2.5 right-3 z-10 rounded-md border border-emerald/40 bg-emerald/15 px-2.5 py-0.5 font-heading text-[10px] font-semibold tracking-wide text-emerald uppercase">
                      Выгодно
                    </span>
                  ) : null}

                  <GlassCard
                    padding="sm"
                    hoverLift={false}
                    className={cn(
                      "border-white/10 bg-white/[0.03]",
                      plan.advantageous && "border-emerald/35 bg-emerald/[0.06]"
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-heading text-base font-semibold text-foreground">
                          {plan.name}
                        </p>
                        <p className="mt-0.5 text-xs text-text-muted">
                          {plan.periodLabel}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <p className="font-heading text-lg font-semibold tabular-nums text-foreground">
                          {formatPrice(plan.priceRub)} ₽
                        </p>
                        <p className="mt-0.5 inline-flex items-center gap-1 text-xs text-text-muted">
                          <Sparkles className="size-3" aria-hidden />
                          {new Intl.NumberFormat("ru-RU").format(plan.coins)}{" "}
                          монет
                        </p>
                      </div>
                    </div>

                    <ul className="mt-3 space-y-1.5">
                      {plan.features.map((feature) => (
                        <li
                          key={feature}
                          className="flex items-start gap-2 text-sm leading-snug text-text-muted"
                        >
                          <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded text-foreground">
                            <Check
                              className="size-3"
                              strokeWidth={2.5}
                              aria-hidden
                            />
                          </span>
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>

                    <GlassButton
                      type="button"
                      className="mt-4 w-full"
                      disabled={Boolean(checkoutCode)}
                      aria-busy={busy}
                      onClick={() => void handleCheckout(plan.tariffCode)}
                    >
                      {busy ? (
                        <>
                          <Loader2
                            className="size-4 animate-spin"
                            aria-hidden
                          />
                          Оформляем…
                        </>
                      ) : (
                        "Выбрать"
                      )}
                    </GlassButton>
                  </GlassCard>
                </li>
              )
            })}
          </ul>
        )}

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
            Закрыть
          </GlassButton>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export { TopUpDialog }
