"use client"

import { Sparkles } from "lucide-react"
import { useRouter } from "next/navigation"
import { useRef } from "react"
import { motion, useInView } from "framer-motion"

import { TropicalLeaves } from "@/components/landing/tropical-leaves"
import { GlassButton } from "@/components/ui/glass-button"

function CallToActionSection() {
  const router = useRouter()
  const sectionRef = useRef<HTMLElement>(null)
  const inView = useInView(sectionRef, { once: true, amount: 0.35 })

  return (
    <section
      id="cta"
      ref={sectionRef}
      className="relative isolate scroll-mt-24 px-5 py-16 sm:py-24"
    >
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-3xl section-glass copper-border">
        {/* Soft emerald wash over glass */}
        <div
          className="absolute inset-0 bg-gradient-to-br from-[#059669]/35 via-[#047857]/20 to-transparent"
          aria-hidden
        />

        <div className="pointer-events-none absolute inset-0" aria-hidden>
          <div className="absolute -left-16 top-1/2 size-64 -translate-y-1/2 rounded-full bg-[#059669]/10 blur-[120px]" />
          <div className="absolute -right-10 -top-20 size-72 rounded-full bg-[#1b3e2b]/20 blur-[120px]" />
          <div className="absolute bottom-0 left-1/3 size-56 rounded-full bg-[#0d0f12]/50 blur-[120px]" />
          <TropicalLeaves className="text-emerald" />
        </div>

        <motion.div
          className="relative flex flex-col items-center px-6 py-14 text-center sm:px-10 sm:py-20"
          initial={{ opacity: 0, y: 28 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 28 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="mb-3 font-heading text-sm font-medium tracking-[0.18em] text-emerald/80 uppercase">
            Старт за минуту
          </p>
          <h2 className="max-w-2xl font-heading text-2xl font-semibold tracking-tight text-foreground sm:text-3xl lg:text-4xl">
            Готовы собрать первую продающую карточку?
          </h2>
          <p className="mt-4 max-w-lg text-sm leading-relaxed text-text-muted sm:text-base">
            Без студии, дизайнеров и подписки на старте — загрузите фото и
            получите карточку для Ozon или WB
          </p>

          <motion.div
            className="mt-9"
            initial={{ opacity: 0, scale: 0.94 }}
            animate={
              inView
                ? { opacity: 1, scale: 1 }
                : { opacity: 0, scale: 0.94 }
            }
            transition={{ delay: 0.15, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          >
            <GlassButton
              size="lg"
              icon={Sparkles}
              className="h-14 gap-2.5 border border-white/20 bg-none bg-white px-8 text-base text-loft shadow-[0_12px_40px_rgba(0,0,0,0.35)] [background-image:none] hover:brightness-105 sm:h-16 sm:px-10 sm:text-lg [&_svg:not([class*='size-'])]:size-5"
              onClick={() => router.push("/register")}
            >
              Создать первую карточку за 0 ₽
            </GlassButton>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

export { CallToActionSection }
