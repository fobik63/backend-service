"use client"

import { AnimatePresence, motion, useReducedMotion } from "framer-motion"
import { Coins, Loader2 } from "lucide-react"
import {
  useEffect,
  useId,
  useMemo,
  useState,
  type FormEvent,
} from "react"
import { toast } from "sonner"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { GlassButton } from "@/components/ui/glass-button"
import { Input } from "@/components/ui/input"
import {
  createCoinPayment,
  getApiErrorMessage,
  listCoinPacks,
} from "@/lib/api"
import { playPaymentSuccessSound } from "@/lib/audio/payment-success"
import {
  COIN_PACKAGES,
  formatCoins,
  formatRub,
  MAX_PURCHASE_COINS,
  MIN_PURCHASE_COINS,
  packageBadge,
  quoteCoinPurchase,
  type CoinPackageSize,
} from "@/lib/billing/coin-pricing"
import {
  savePendingCoinPurchase,
  takePendingCoinPurchase,
} from "@/lib/billing/pending-coin-purchase"
import { IS_MOCK } from "@/lib/constants/mock"
import { useAuthStore } from "@/lib/store"
import { cn } from "@/lib/utils"

const EASE_OUT = [0.23, 1, 0.32, 1] as const

type BuyCoinsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpenTariffs?: () => void
}

function parseCoinInput(raw: string): number | null {
  const digits = raw.replace(/\D/g, "")
  if (!digits) return null
  const value = Number.parseInt(digits, 10)
  if (!Number.isFinite(value)) return null
  return Math.min(value, MAX_PURCHASE_COINS)
}

function BuyCoinsDialog({
  open,
  onOpenChange,
  onOpenTariffs,
}: BuyCoinsDialogProps) {
  const inputId = useId()
  const hintId = useId()
  const reduceMotion = useReducedMotion()
  const user = useAuthStore((s) => s.user)
  const creditAiCoins = useAuthStore((s) => s.creditAiCoins)

  const [rawAmount, setRawAmount] = useState(String(MIN_PURCHASE_COINS))
  const [touched, setTouched] = useState(false)
  const [paying, setPaying] = useState(false)
  const [packPrices, setPackPrices] = useState<Record<number, number>>({})

  const amountCoins = parseCoinInput(rawAmount)
  const belowMinimum =
    amountCoins !== null && amountCoins < MIN_PURCHASE_COINS
  const empty = amountCoins === null
  const invalid = empty || belowMinimum
  const showHint = touched && invalid

  const quote = useMemo(() => {
    if (amountCoins === null || amountCoins < MIN_PURCHASE_COINS) return null
    return quoteCoinPurchase(amountCoins)
  }, [amountCoins])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    void listCoinPacks()
      .then((packs) => {
        if (cancelled) return
        const next: Record<number, number> = {}
        for (const pack of packs) {
          const rub = Number.parseFloat(pack.amount_rub)
          if (Number.isFinite(rub)) next[pack.amount_coins] = rub
        }
        setPackPrices(next)
      })
      .catch(() => {
        /* local quote remains the source of truth */
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const selectPreset = (size: CoinPackageSize) => {
    setRawAmount(String(size))
    setTouched(true)
  }

  const handlePay = async (event: FormEvent) => {
    event.preventDefault()
    setTouched(true)
    if (!quote || paying) return
    if (!user?.id) {
      toast.error("Войдите в аккаунт, чтобы купить коины.")
      return
    }

    setPaying(true)
    savePendingCoinPurchase({
      amountCoins: quote.amountCoins,
      amountRub: quote.amountRub,
    })
    /* Optimistic: pending row is local-first; balance credits on return. */
    try {
      const payment = await createCoinPayment(user.id, quote.amountCoins)
      if (!payment.confirmation_url) {
        toast.error(
          "Платёжный провайдер недоступен: confirmation_url не получен."
        )
        setPaying(false)
        return
      }
      if (IS_MOCK) {
        takePendingCoinPurchase()
        creditAiCoins(quote.amountCoins)
        toast.success(`Зачислено ${formatCoins(quote.amountCoins)} коинов`)
        void playPaymentSuccessSound()
        setPaying(false)
        onOpenChange(false)
        return
      }
      window.location.assign(payment.confirmation_url)
    } catch (error) {
      setPaying(false)
      toast.error(
        getApiErrorMessage(
          error,
          "Не удалось создать платёж. Проверьте настройки ЮKassa."
        )
      )
    }
  }

  const motionTransition = reduceMotion
    ? { duration: 0.01 }
    : { duration: 0.22, ease: EASE_OUT }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(90dvh,40rem)] w-full overflow-y-auto sm:max-w-lg"
        showCloseButton
      >
        <DialogHeader>
          <DialogTitle>Покупка ИИ-коинов</DialogTitle>
          <DialogDescription>
            Минимум {MIN_PURCHASE_COINS} коинов. Итог в рублях пересчитывается
            сразу — оплата через ЮKassa.
          </DialogDescription>
        </DialogHeader>

        {typeof user?.ai_coins === "number" ? (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3">
            <div className="flex items-center gap-2 text-sm text-text-muted">
              <Coins className="size-4 text-amber" aria-hidden />
              <span>Текущий баланс</span>
            </div>
            <p className="font-heading text-sm font-semibold tabular-nums text-foreground">
              {formatCoins(user.ai_coins)} коинов
            </p>
          </div>
        ) : null}

        <form onSubmit={(event) => void handlePay(event)} className="space-y-4">
          <div className="space-y-2">
            <label
              htmlFor={inputId}
              className="font-heading text-xs font-medium text-foreground"
            >
              Количество коинов
            </label>
            <div className="relative">
              <Input
                id={inputId}
                inputMode="numeric"
                autoComplete="off"
                aria-invalid={showHint}
                aria-describedby={showHint ? hintId : undefined}
                value={rawAmount}
                onChange={(event) => {
                  const next = event.target.value.replace(/\D/g, "")
                  setRawAmount(next)
                }}
                onBlur={() => setTouched(true)}
                className="h-12 pr-20 text-base tabular-nums md:text-base"
                placeholder={String(MIN_PURCHASE_COINS)}
              />
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-text-muted">
                коинов
              </span>
            </div>
            <AnimatePresence>
              {showHint ? (
                <motion.p
                  key="min-coins-hint"
                  id={hintId}
                  role="alert"
                  initial={
                    reduceMotion
                      ? { opacity: 0 }
                      : { opacity: 0, transform: "translateY(-4px)" }
                  }
                  animate={
                    reduceMotion
                      ? { opacity: 1 }
                      : { opacity: 1, transform: "translateY(0px)" }
                  }
                  exit={
                    reduceMotion
                      ? { opacity: 0 }
                      : { opacity: 0, transform: "translateY(-4px)" }
                  }
                  transition={motionTransition}
                  className="text-sm text-destructive"
                >
                  Минимум {MIN_PURCHASE_COINS} коинов. Введите{" "}
                  {MIN_PURCHASE_COINS} или больше, чтобы продолжить оплату.
                </motion.p>
              ) : null}
            </AnimatePresence>
          </div>

          <div>
            <p className="mb-2 text-xs text-text-muted">Быстрый выбор</p>
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {COIN_PACKAGES.map((size, index) => {
                const selected = amountCoins === size
                const badge = packageBadge(size)
                const featured = size >= 1000
                const packRub =
                  packPrices[size] ?? quoteCoinPurchase(size).amountRub
                return (
                  <li key={size} className="min-h-11">
                    <motion.button
                      type="button"
                      initial={
                        reduceMotion
                          ? false
                          : { opacity: 0, transform: "translateY(6px)" }
                      }
                      animate={{ opacity: 1, transform: "translateY(0px)" }}
                      transition={{
                        ...motionTransition,
                        delay: reduceMotion ? 0 : index * 0.04,
                      }}
                      whileTap={
                        reduceMotion
                          ? undefined
                          : { transform: "scale(0.97)" }
                      }
                      onClick={() => selectPreset(size)}
                      aria-pressed={selected}
                      className={cn(
                        "relative flex h-full min-h-11 w-full cursor-pointer flex-col items-start rounded-xl border px-3 py-2.5 text-left outline-none",
                        "transition-[border-color,box-shadow,background-color] duration-200",
                        "focus-visible:ring-2 focus-visible:ring-ring/50",
                        selected
                          ? "border-foreground/35 bg-white/[0.06]"
                          : "border-white/10 bg-white/[0.03]",
                        featured &&
                          "emerald-glow border-foreground/40 ring-1 ring-foreground/25"
                      )}
                    >
                      {badge ? (
                        <span className="absolute -top-2 right-2 rounded-md border border-foreground/25 bg-loft px-1.5 py-0.5 font-heading text-[9px] font-semibold tracking-wide text-foreground uppercase">
                          {badge}
                        </span>
                      ) : null}
                      <span className="font-heading text-sm font-semibold tabular-nums text-foreground">
                        {formatCoins(size)}
                      </span>
                      <span className="mt-0.5 text-[11px] tabular-nums text-text-muted">
                        {formatRub(packRub)} ₽
                      </span>
                    </motion.button>
                  </li>
                )
              })}
            </ul>
          </div>

          <div
            className="flex items-end justify-between gap-3 rounded-xl border border-white/10 bg-loft/50 px-3.5 py-3"
            aria-live="polite"
          >
            <div>
              <p className="text-xs text-text-muted">К оплате</p>
              <p className="font-heading text-xl font-semibold tabular-nums text-foreground">
                {quote ? `${formatRub(quote.amountRub)} ₽` : "—"}
              </p>
            </div>
            {quote ? (
              <p className="text-right text-[11px] text-text-muted">
                {formatRub(quote.unitPriceRub)} ₽ за коин
              </p>
            ) : null}
          </div>

          <GlassButton
            type="submit"
            className="relative h-12 w-full overflow-hidden"
            disabled={invalid || paying}
            aria-busy={paying}
          >
            {paying ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Переходим к ЮKassa…
              </span>
            ) : (
              "Оплатить через ЮKassa"
            )}
            {paying ? (
              <span
                className="absolute inset-0 animate-pulse bg-foreground/10"
                aria-hidden
              />
            ) : null}
          </GlassButton>
        </form>

        {onOpenTariffs ? (
          <button
            type="button"
            onClick={() => {
              onOpenChange(false)
              onOpenTariffs()
            }}
            className="w-full cursor-pointer text-center text-xs text-text-muted underline-offset-4 hover:text-foreground hover:underline"
          >
            Нужна подписка? Открыть тарифы
          </button>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export { BuyCoinsDialog }
export type { BuyCoinsDialogProps }
