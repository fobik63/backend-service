"use client"

import { motion, useReducedMotion } from "framer-motion"
import { Check, Loader2 } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"

import { GlassButton } from "@/components/ui/glass-button"
import { fetchCurrentUser } from "@/lib/api/auth"
import { playPaymentSuccessSound } from "@/lib/audio/payment-success"
import { formatCoins } from "@/lib/billing/coin-pricing"
import { takePendingCoinPurchase } from "@/lib/billing/pending-coin-purchase"
import { persistUser } from "@/lib/auth/session"
import { IS_MOCK } from "@/lib/constants/mock"
import { useAuthStore } from "@/lib/store"

const EASE_OUT = [0.23, 1, 0.32, 1] as const

function PaymentReturnView() {
  const router = useRouter()
  const reduceMotion = useReducedMotion()
  const hydrated = useAuthStore((s) => s.hydrated)
  const setUser = useAuthStore((s) => s.setUser)
  const creditAiCoins = useAuthStore((s) => s.creditAiCoins)
  const applied = useRef(false)
  const [credited, setCredited] = useState<number | null>(null)
  const [busy, setBusy] = useState(true)

  useEffect(() => {
    if (!hydrated || applied.current) return
    applied.current = true

    const pending = takePendingCoinPurchase()
    const before = useAuthStore.getState().user?.ai_coins ?? 0
    if (pending) {
      creditAiCoins(pending.amountCoins)
      setCredited(pending.amountCoins)
      void playPaymentSuccessSound()
    }

    let cancelled = false
    void (async () => {
      if (!IS_MOCK) {
        try {
          const profile = await fetchCurrentUser()
          if (cancelled) return
          const optimistic = before + (pending?.amountCoins ?? 0)
          const merged = {
            ...profile,
            ai_coins: Math.max(profile.ai_coins, optimistic),
          }
          persistUser(merged)
          setUser(merged)
        } catch {
          /* keep optimistic local balance */
        }
      }
      if (!cancelled) setBusy(false)
    })()

    return () => {
      cancelled = true
    }
  }, [hydrated, creditAiCoins, setUser])

  const goWorkspace = () => {
    void playPaymentSuccessSound()
    router.replace("/projects")
  }

  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center px-4 py-16">
      <motion.div
        initial={
          reduceMotion
            ? { opacity: 0 }
            : { opacity: 0, transform: "scale(0.96)" }
        }
        animate={{ opacity: 1, transform: "scale(1)" }}
        transition={
          reduceMotion
            ? { duration: 0.01 }
            : { duration: 0.24, ease: EASE_OUT }
        }
        className="w-full rounded-xl border border-white/10 bg-zinc-900/60 p-6 text-center backdrop-blur-xl"
      >
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full border border-foreground/20 bg-white/[0.06]">
          {busy && credited === null ? (
            <Loader2 className="size-5 animate-spin text-foreground" />
          ) : (
            <Check className="size-5 text-foreground" aria-hidden />
          )}
        </div>
        <h1 className="font-heading text-lg font-semibold text-foreground">
          {credited
            ? "Оплата прошла"
            : busy
              ? "Проверяем платёж"
              : "Возврат из ЮKassa"}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-text-muted">
          {credited
            ? `На баланс зачислено ${formatCoins(credited)} ИИ-коинов. Если вебхук ещё в пути, сумма уже показана локально.`
            : "Если деньги списались, коины появятся на балансе после подтверждения ЮKassa."}
        </p>
        <GlassButton
          type="button"
          className="mt-6 w-full"
          onClick={goWorkspace}
        >
          В кабинет
        </GlassButton>
      </motion.div>
    </div>
  )
}

export { PaymentReturnView }
