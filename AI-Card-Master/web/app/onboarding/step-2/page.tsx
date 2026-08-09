"use client"

import { useState } from "react"
import { Check } from "lucide-react"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"

import { CategoryChip } from "@/components/onboarding"
import { GlassButton } from "@/components/ui/glass-button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useOnboardingStore,
  type OnboardingCategory,
} from "@/lib/store"

const CATEGORIES: { id: OnboardingCategory; label: string }[] = [
  { id: "footwear_clothing", label: "Обувь и одежда" },
  { id: "electronics", label: "Электроника" },
  { id: "cosmetics", label: "Косметика" },
  { id: "home_garden", label: "Дом и сад" },
  { id: "auto", label: "Автотовары" },
  { id: "kids", label: "Детские товары" },
]

const FINISH_DELAY_MS = 1400

function OnboardingFinishSkeleton() {
  return (
    <div
      className="flex flex-col gap-8"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label="Сохраняем настройки"
    >
      <header className="space-y-3 text-center sm:text-left">
        <Skeleton className="mx-auto h-3 w-24 sm:mx-0" />
        <Skeleton className="mx-auto h-8 w-4/5 max-w-md sm:mx-0" />
        <Skeleton className="mx-auto h-4 w-3/5 max-w-sm sm:mx-0" />
      </header>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full rounded-xl" />
        ))}
      </div>

      <Skeleton className="h-12 w-full rounded-lg sm:ml-auto sm:w-52" />
      <span className="sr-only">Сохраняем настройки и открываем личный кабинет…</span>
    </div>
  )
}

export default function OnboardingStep2Page() {
  const router = useRouter()
  const [isFinishing, setIsFinishing] = useState(false)
  const categories = useOnboardingStore((s) => s.categories)
  const toggleCategory = useOnboardingStore((s) => s.toggleCategory)

  const handleFinish = () => {
    if (categories.length === 0 || isFinishing) return

    setIsFinishing(true)

    window.setTimeout(() => {
      router.push("/projects")
    }, FINISH_DELAY_MS)
  }

  if (isFinishing) {
    return <OnboardingFinishSkeleton />
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col gap-8"
    >
      <header className="space-y-2 text-center sm:text-left">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald">
          Шаг 2 из 2
        </p>
        <h1 className="font-heading text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Какую категорию товаров вы продвигаете?
        </h1>
        <p className="text-sm text-text-muted sm:text-base">
          Можно выбрать несколько — подстроим шаблоны и подсказки под вашу нишу.
        </p>
      </header>

      <div
        className="grid grid-cols-1 gap-3 sm:grid-cols-2"
        role="group"
        aria-label="Категории товаров"
      >
        {CATEGORIES.map((category, index) => (
          <motion.div
            key={category.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.05 * index,
              duration: 0.3,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <CategoryChip
              label={category.label}
              selected={categories.includes(category.id)}
              onToggle={() => toggleCategory(category.id)}
            />
          </motion.div>
        ))}
      </div>

      <GlassButton
        size="lg"
        className="w-full sm:ml-auto sm:w-auto"
        disabled={categories.length === 0}
        icon={Check}
        iconPosition="end"
        onClick={handleFinish}
      >
        Завершить настройку
      </GlassButton>
    </motion.div>
  )
}
