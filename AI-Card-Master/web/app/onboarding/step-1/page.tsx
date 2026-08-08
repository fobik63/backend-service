"use client"

import { ArrowRight } from "lucide-react"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"

import {
  MarketplaceOptionCard,
  OzonLogo,
  WildberriesLogo,
} from "@/components/onboarding"
import { GlassButton } from "@/components/ui/glass-button"
import {
  useOnboardingStore,
  type OnboardingMarketplace,
} from "@/lib/store"

const OPTIONS: {
  id: OnboardingMarketplace
  title: string
  description?: string
  logoCaption?: string
}[] = [
  {
    id: "ozon",
    title: "Ozon",
    description: "Карточки 1080x1440, рич-контент",
  },
  {
    id: "wildberries",
    title: "Wildberries",
    description: "Вертикальный формат 3:4, акцентная инфографика",
  },
  {
    id: "both",
    title: "Продаю на обоих маркетплейсах",
    logoCaption: "Продаю на обоих маркетплейсах",
  },
]

function OptionLogos({ id }: { id: OnboardingMarketplace }) {
  if (id === "ozon") {
    return <OzonLogo />
  }

  if (id === "wildberries") {
    return <WildberriesLogo />
  }

  return (
    <div className="flex flex-wrap items-center gap-3 sm:gap-4">
      <OzonLogo className="h-7 sm:h-8" />
      <span
        className="font-heading text-sm font-medium text-text-muted"
        aria-hidden
      >
        +
      </span>
      <WildberriesLogo className="h-6 sm:h-7" />
    </div>
  )
}

export default function OnboardingStep1Page() {
  const router = useRouter()
  const marketplace = useOnboardingStore((s) => s.marketplace)
  const setMarketplace = useOnboardingStore((s) => s.setMarketplace)

  const handleNext = () => {
    if (!marketplace) return
    router.push("/onboarding/step-2")
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
          Шаг 1 из 2
        </p>
        <h1 className="font-heading text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Где вы продаете свои товары?
        </h1>
        <p className="text-sm text-text-muted sm:text-base">
          Выберите маркетплейс — под него настроим формат карточек и шаблоны.
        </p>
      </header>

      <div
        className="flex flex-col gap-3"
        role="group"
        aria-label="Выбор маркетплейса"
      >
        {OPTIONS.map((option, index) => (
          <motion.div
            key={option.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.06 * index,
              duration: 0.3,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <MarketplaceOptionCard
              title={option.title}
              description={option.description}
              logoCaption={option.logoCaption}
              selected={marketplace === option.id}
              onSelect={() => setMarketplace(option.id)}
              logos={<OptionLogos id={option.id} />}
            />
          </motion.div>
        ))}
      </div>

      <GlassButton
        size="lg"
        className="w-full sm:ml-auto sm:w-auto"
        disabled={!marketplace}
        icon={ArrowRight}
        iconPosition="end"
        onClick={handleNext}
      >
        Далее
      </GlassButton>
    </motion.div>
  )
}
