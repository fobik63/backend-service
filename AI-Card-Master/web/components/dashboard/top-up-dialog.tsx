"use client"

import { Check, Loader2, Sparkles } from "lucide-react"
import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
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
import {
  createPayment,
  getApiErrorMessage,
  listTariffs,
  type TariffCode,
  type TariffDTO,
} from "@/lib/api"
import { cn } from "@/lib/utils"

type BillingPeriod = "week" | "month" | "half_year" | "year"

const PERIODS: { id: BillingPeriod; label: string }[] = [
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "half_year", label: "6 мес." },
  { id: "year", label: "Год" },
]

const PERIOD_BY_CODE: Record<string, BillingPeriod> = {
  start: "week",
  pro: "month",
  half_year: "half_year",
  year: "year",
}

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
  const [tariffs, setTariffs] = useState<TariffDTO[] | null>(null)
  const [checkoutCode, setCheckoutCode] = useState<string | null>(null)
  const loading = open && tariffs === null

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void listTariffs()
      .then((items) => {
        if (!cancelled) setTariffs(items)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setTariffs([])
        toast.error(
          getApiErrorMessage(error, "Не удалось загрузить тарифы для оплаты")
        )
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const plans = useMemo(
    () =>
      (tariffs ?? []).filter((plan) => PERIOD_BY_CODE[plan.code] === period),
    [period, tariffs]
  )

  const handleCheckout = async (tariffCode: string) => {
    if (checkoutCode) return
    setCheckoutCode(tariffCode)
    try {
      const payment = await createPayment(tariffCode as TariffCode)
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
        className="max-h-[min(90dvh,40rem)] w-full overflow-y-auto sm:max-w-lg"
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

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Загружаем тарифы…
          </div>
        ) : plans.length === 0 ? (
          <p className="rounded-xl border border-amber/30 bg-amber/10 px-3 py-4 text-sm text-foreground">
            Для выбранного периода нет доступных тарифов.
          </p>
        ) : (
          <ul className="space-y-2">
            {plans.map((plan) => {
              const highlighted = plan.code === "pro" || plan.code === "year"
              const busy = checkoutCode === plan.code
              return (
                <li key={plan.code}>
                  <button
                    type="button"
                    disabled={Boolean(checkoutCode)}
                    aria-busy={busy}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl border px-3.5 py-3 text-left transition-colors",
                      highlighted
                        ? "border-emerald/40 bg-emerald/10"
                        : "border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05]",
                      "disabled:opacity-60"
                    )}
                    onClick={() => void handleCheckout(plan.code)}
                  >
                    <span
                      className={cn(
                        "flex size-8 shrink-0 items-center justify-center rounded-lg",
                        highlighted
                          ? "bg-emerald/20 text-emerald"
                          : "bg-white/5 text-copper"
                      )}
                    >
                      {busy ? (
                        <Loader2 className="size-4 animate-spin" aria-hidden />
                      ) : highlighted ? (
                        <Sparkles className="size-4" aria-hidden />
                      ) : (
                        <Check className="size-4" aria-hidden />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-heading text-sm font-semibold text-foreground">
                        {plan.title}
                      </span>
                      <span className="block text-xs text-text-muted">
                        {new Intl.NumberFormat("ru-RU").format(plan.ai_coins)}{" "}
                        монет
                      </span>
                    </span>
                    <span className="font-heading text-sm font-semibold tabular-nums text-foreground">
                      {formatPrice(plan.price_rub)} ₽
                    </span>
                  </button>
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
